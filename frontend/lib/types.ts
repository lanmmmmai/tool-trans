export interface Project {
  id: string;
  user_id: string;
  title: string;
  source_language: string;
  target_language: string;
  status: string;
  audio_mode: string;
  translate_engine: string | null;
  created_at: string;
  updated_at: string;
}
