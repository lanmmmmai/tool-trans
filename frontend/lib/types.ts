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

export interface TranscriptSegment {
  id: string;
  project_id: string;
  seq_index: number;
  start_time: number;
  end_time: number;
  speaker_label: string;
  source_text: string;
  source_text_edited: string | null;
  confidence: number | null;
}

export interface TranslationSegment {
  id: string;
  segment_id: string;
  seq_index: number;
  start_time: number;
  end_time: number;
  speaker_label: string;
  source_text: string;
  translated_text: string;
  translated_text_edited: string | null;
}

export interface VoiceCatalogEntry {
  voice_id: string;
  name: string;
  gender: string;
  engine: string;
}

export interface VoiceAssignment {
  speaker_label: string;
  engine: string;
  voice_id: string;
  speed: number;
  pitch: number;
}
