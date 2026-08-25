"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  login as apiLogin,
  logout as apiLogout,
  refresh as apiRefresh,
  registerUser as apiRegister,
  type User,
} from "./auth-api";

type AuthContextValue = {
  user: User | null;
  accessToken: string | null;
  initializing: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    // Silent refresh on load: the access token lives only in memory (never
    // localStorage/sessionStorage — see CLAUDE.md §8), so a full page reload
    // always starts with none. The httpOnly refresh cookie set at login is
    // what lets this recover a session without the user re-entering a
    // password.
    apiRefresh()
      .then((data) => {
        setAccessToken(data.access_token);
        setUser(data.user);
      })
      .catch(() => {
        setAccessToken(null);
        setUser(null);
      })
      .finally(() => setInitializing(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiLogin(email, password);
    setAccessToken(data.access_token);
    setUser(data.user);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    await apiRegister(email, password);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setAccessToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, accessToken, initializing, login, register, logout }),
    [user, accessToken, initializing, login, register, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
