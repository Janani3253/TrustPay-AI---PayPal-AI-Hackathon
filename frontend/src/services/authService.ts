import { api } from './api'

export interface DemoUser {
  id: number
  name: string
  email: string
}

interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  user: DemoUser
}

const accessTokenKey = 'trustpay-access-token'

function saveAuth(response: AuthResponse): DemoUser {
  localStorage.setItem(accessTokenKey, response.access_token)
  return response.user
}

export async function login(email: string, password: string): Promise<DemoUser> {
  const response = await api.post<AuthResponse>('/auth/login', { email, password })
  return saveAuth(response.data)
}

export async function register(name: string, email: string, password: string): Promise<DemoUser> {
  const response = await api.post<AuthResponse>('/auth/register', { name, email, password })
  return saveAuth(response.data)
}

export async function getCurrentUser(): Promise<DemoUser> {
  const response = await api.get<DemoUser>('/auth/me')
  return response.data
}

export async function logout(): Promise<void> {
  try {
    await api.post('/auth/logout')
  } finally {
    clearAuthToken()
  }
}

export function clearAuthToken(): void {
  localStorage.removeItem(accessTokenKey)
}
