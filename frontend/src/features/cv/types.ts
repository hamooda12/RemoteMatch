export type CVParseStatus =
  | "pending"
  | "processed"
  | "failed";

export type CVDocument = {
  user_id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  parse_status: CVParseStatus;
  created_at: string;
  updated_at: string;
};

export type CVTextResponse = {
  user_id: string;
  parse_status: CVParseStatus;
  extracted_text: string;
  character_count: number;
};

export type CVSkillsResponse = {
  user_id: string;
  skills: string[];
  skill_count: number;
  extraction_version: string;
};