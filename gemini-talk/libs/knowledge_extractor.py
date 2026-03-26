"""
gemini-talk 知识抽取与存储
- 向量数据库: Chroma (轻量级，内置)
- 知识图谱三元组存储: SQLite (轻量级，无需额外服务)
- 双库联动: Chroma 向量检索 + SQLite 三元组，互相索引
"""

import os
import re
import json
import sqlite3
import datetime
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

import chromadb
from chromadb.config import Settings

@dataclass
class KnowledgeTriple:
    subject: str
    predicate: str
    obj: str
    confidence: float
    source_session: str
    timestamp: str
    vector_id: Optional[str] = None  # 关联 Chroma vector id

@dataclass
class DocumentChunk:
    content: str
    metadata: Dict
    embedding: Optional[List[float]] = None

class KnowledgeBase:
    def __init__(self, data_dir: str = "~/.openclaw/skills/gemini-talk/data"):
        self.data_dir = os.path.expanduser(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 1. 初始化 Chroma 向量数据库
        self.chroma_client = chromadb.PersistentClient(
            path=os.path.join(self.data_dir, "chroma"),
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="gemini_talk_knowledge",
            metadata={"hnsw:space": "cosine"}
        )
        
        # 2. 初始化 SQLite 三元组存储
        self._init_sqlite()
    
    def _init_sqlite(self):
        """初始化 SQLite 表结构（增加 vector_id 关联 Chroma）"""
        db_path = os.path.join(self.data_dir, "knowledge_triples.db")
        self.conn = sqlite3.connect(db_path)
        cursor = self.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS triples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                obj TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_session TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                vector_id TEXT        -- 关联 Chroma 向量 chunk id
            )
        """)
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subject ON triples(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_predicate ON triples(predicate)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vector_id ON triples(vector_id)")
        self.conn.commit()
    
    def extract_knowledge_from_dialog(self, dialog_history: List[Dict], session_id: str, 
                                       llm_extract: Optional[List[Dict]] = None) -> Tuple[List[DocumentChunk], List[KnowledgeTriple]]:
        """从对话历史抽取知识
        llm_extract: 如果提供，使用 LLM 抽取的结果 (JSON 格式 [{"subject":..., "predicate":..., "obj":...}])
        """
        chunks = []
        triples = []
        
        # 1. 清洗对话：过滤掉打招呼、礼貌语
        cleaned_dialog = self._clean_dialog(dialog_history)
        
        # 2. 分块：每轮对话作为一个 chunk
        for i, turn in enumerate(cleaned_dialog):
            role = turn.get("role", "unknown")
            content = turn.get("content", "").strip()
            
            if len(content) < 10:
                continue  # 跳过太短的
            
            chunk_id = f"chunk_{hash(content + datetime.datetime.now().isoformat())}"
            chunk = DocumentChunk(
                content=content,
                metadata={
                    "role": role,
                    "session_id": session_id,
                    "turn_index": i,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
            chunks.append(chunk)
        
        # 3. 抽取三元组：优先使用 LLM (Gemini) 抽取，降级启发式
        if llm_extract:
            # LLM 驱动抽取（推荐方式，准确率高）
            timestamp = datetime.datetime.now().isoformat()
            for i, item in enumerate(llm_extract):
                triple = KnowledgeTriple(
                    subject=item.get("subject", ""),
                    predicate=item.get("predicate", ""),
                    obj=item.get("obj", ""),
                    confidence=item.get("confidence", 0.9),
                    source_session=session_id,
                    timestamp=timestamp,
                    vector_id=chunks[i].metadata.get("id", chunk_id) if i < len(chunks) else None
                )
                triples.append(triple)
        else:
            # 降级：启发式抽取（不推荐，仅简单结论有效）
            for turn in cleaned_dialog:
                content = turn.get("content", "").strip()
                extracted = self._extract_triples_heuristic(content, session_id)
                # 关联 chunk id
                for t in extracted:
                    if chunks:
                        t.vector_id = chunks[-1].metadata.get("id", chunk_id)
                triples.extend(extracted)
        
        # 4. 给 chunks 加上 sqlite_row_id 元数据（双向索引）
        for i, chunk in enumerate(chunks):
            if i < len(triples):
                chunk.metadata["sqlite_row_id"] = i + 1  # SQLite id 从 1 开始
        
        return chunks, triples
    
    def _clean_dialog(self, dialog_history: List[Dict]) -> List[Dict]:
        """清洗对话，去除无意义内容"""
        skip_patterns = [
            r"^你好$", r"^您好$", r"^谢谢$", r"^谢谢了$",
            r"^好的$", r"^没问题$", r"^嗯$", r"^ok$", r"^OK$"
        ]
        cleaned = []
        for turn in dialog_history:
            content = turn.get("content", "").strip()
            if not content:
                continue
            skip = False
            for pat in skip_patterns:
                if re.match(pat, content.lower()):
                    skip = True
                    break
            if not skip:
                cleaned.append(turn)
        return cleaned
    
    def _extract_triples_heuristic(self, text: str, session_id: str) -> List[KnowledgeTriple]:
        """启发式抽取三元组（降级方案）
        如果文本已经是结论性语句，抽取(主体, 关系, 客体)
        """
        triples = []
        timestamp = datetime.datetime.now().isoformat()
        
        # 启发式抽取：匹配 "X 是 Y"、"X 使用 Y"、"X 的 Y 是 Z" 等模式
        patterns = [
            (r"(\w+)\s+是\s+(.+)", "是"),
            (r"(\w+)\s+使用\s+(.+)", "使用"),
            (r"(\w+)\s+偏好\s+(.+)", "偏好"),
            (r"(\w+)\s+的\s+(\w+)\s+是\s+(.+)", None),  # 处理 "X 的 Y 是 Z" → (X, Y, Z)
        ]
        
        for pattern, predicate in patterns:
            matches = list(re.finditer(pattern, text))
            for match in matches:
                if predicate is None and len(match.groups()) == 3:
                    # "X 的 Y 是 Z"
                    subject = match.group(1).strip()
                    pred = match.group(2).strip()
                    obj = match.group(3).strip()
                    triples.append(KnowledgeTriple(
                        subject=subject, predicate=pred, obj=obj,
                            confidence=0.8, source_session=session_id, timestamp=timestamp
                    ))
                else:
                    subject = match.group(1).strip()
                    obj = match.group(2).strip()
                    triples.append(KnowledgeTriple(
                        subject=subject, predicate=predicate, obj=obj,
                            confidence=0.7, source_session=session_id, timestamp=timestamp
                    ))
        
        return triples
    
    def get_llm_extraction_prompt(self, dialog_text: str) -> str:
        """生成给 Gemini 的抽取提示
        让 Gemini 自己抽取对话知识三元组，返回 JSON 数组
        """
        return f"""请从下面的对话中抽取知识三元组，格式为 JSON 数组：
[
  {{
    "subject": "主体实体",
    "predicate": "关系", 
    "obj": "客体实体",
    "confidence": 0.9
  }}
]

只返回 JSON，不要其他解释。置信度 0.0-1.0，表示你对这个三元组的确信程度。

对话内容：
{dialog_text}
"""
    
    def store_knowledge(self, chunks: List[DocumentChunk], triples: List[KnowledgeTriple]):
        """存储知识到向量数据库和 SQLite（双库联动）"""
        # 1. 存储向量块到 Chroma，加上 sqlite_row_id 元数据
        if chunks:
            ids = []
            documents = []
            metadatas = []
            for i, c in enumerate(chunks):
                chunk_id = f"chunk_{hash(c.content + c.metadata['timestamp'])}"
                ids.append(chunk_id)
                documents.append(c.content)
                # 增加 sqlite_row_id 关联
                if i < len(triples):
                    c.metadata["sqlite_row_id"] = i + 1  # SQLite id 从 1 开始
                metadatas.append(c.metadata)
            
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
        
        # 2. 存储三元组到 SQLite，加上 vector_id 关联
        if triples:
            cursor = self.conn.cursor()
            for t in triples:
                cursor.execute("""
                    INSERT INTO triples (subject, predicate, obj, confidence, source_session, timestamp, vector_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (t.subject, t.predicate, t.obj, t.confidence, t.source_session, t.timestamp, t.vector_id))
            self.conn.commit()
    
    def search_with_triples(self, query: str, top_k: int = 5) -> Dict:
        """向量检索 + 关联三元组查询
        返回：向量召回结果 + 关联的知识三元组
        """
        # 1. Chroma 向量召回
        vector_results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )
        
        # 2. 从 SQLite 加载关联的三元组
        linked_triples = []
        for i, (doc, meta) in enumerate(zip(
            vector_results["documents"][0],
            vector_results["metadatas"][0]
        )):
            sqlite_row_id = meta.get("sqlite_row_id")
            if sqlite_row_id:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM triples WHERE id = ?", (sqlite_row_id,))
                row = cursor.fetchone()
                if row:
                    linked_triples.append({
                        "id": row[0],
                        "subject": row[1],
                        "predicate": row[2],
                        "obj": row[3],
                        "confidence": row[4],
                        "source_session": row[5],
                        "timestamp": row[6],
                        "vector_id": row[7]
                    })
        
        return {
            "vector_chunks": [
                {
                    "content": doc,
                    "metadata": meta,
                    "distance": dist
                }
                for doc, meta, dist in zip(
                    vector_results["documents"][0],
                    vector_results["metadatas"][0],
                    vector_results["distances"][0]
                )
            ],
            "linked_triples": linked_triples
        }
    
    def search_similar(self, query: str, top_k: int = 5) -> List[Dict]:
        """语义相似度搜索（仅向量）"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )
        return [
            {
                "content": doc,
                "metadata": meta,
                "distance": dist
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            )
        ]
    
    def query_triples(self, subject: Optional[str] = None, predicate: Optional[str] = None) -> List[Dict]:
        """查询三元组"""
        cursor = self.conn.cursor()
        sql = "SELECT * FROM triples WHERE 1=1"
        params = []
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        if predicate:
            sql += " AND predicate = ?"
            params.append(predicate)
        sql += " ORDER BY confidence DESC"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        return [
            {
                "id": row[0],
                "subject": row[1],
                "predicate": row[2],
                "obj": row[3],
                "confidence": row[4],
                "source_session": row[5],
                "timestamp": row[6],
                "vector_id": row[7]
            }
            for row in rows
        ]
    
    def close(self):
        self.conn.close()

def async_extract_to_knowledge_base(dialog_history: List[Dict], session_id: str, llm_extract: Optional[List[Dict]] = None):
    """异步抽取入口（给 gemini-talk 调用）"""
    kb = KnowledgeBase()
    try:
        chunks, triples = kb.extract_knowledge_from_dialog(dialog_history, session_id, llm_extract)
        kb.store_knowledge(chunks, triples)
        kb.close()
        return {
            "status": "ok",
            "chunks_extracted": len(chunks),
            "triples_extracted": len(triples)
        }
    except Exception as e:
        kb.close()
        return {
            "status": "error",
            "error": str(e)
        }
