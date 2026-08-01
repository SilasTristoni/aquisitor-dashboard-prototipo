import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";

export type User = { id: number; name: string; email: string; role: "admin" | "operator" | "viewer" };
type AuthContextValue = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!localStorage.getItem("thermopower.token")) {
      setLoading(false);
      return;
    }
    api<User>("/auth/me").then(setUser).catch(() => localStorage.removeItem("thermopower.token")).finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    async login(email, password) {
      const response = await api<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      localStorage.setItem("thermopower.token", response.access_token);
      setUser(response.user);
    },
    logout() {
      localStorage.removeItem("thermopower.token");
      setUser(null);
    },
  }), [user, loading]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth deve estar dentro de AuthProvider");
  return value;
}
