export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  auth_provider: string;
  created_at: string;
  last_login_at: string | null;
};

export type RegisterInput = {
  email: string;
  display_name: string;
  password: string;
};

export type LoginInput = {
  email: string;
  password: string;
};

export type MessageResponse = {
  message: string;
};