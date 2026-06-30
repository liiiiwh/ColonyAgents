export interface StorageObject {
  key: string;
  size: number;
  last_modified: string;
}

export interface KnowledgeBasePublic {
  id: string;
  name: string;
  description: string;
  collection_name: string;
  embedding_model_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentPublic {
  id: string;
  kb_id: string;
  filename: string;
  s3_key: string;
  chunk_count: number;
  status: 'pending' | 'indexing' | 'indexed' | 'failed';
  created_at: string;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string | null;
  score: number;
  content: string;
  meta: Record<string, unknown>;
}
