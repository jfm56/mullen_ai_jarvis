"use client";

/**
 * Auth context.
 *
 * - Holds the current `User` (or null) and a loading flag.
 * - Listens for `jarvis:auth-changed` window events so that `setToken` /
 *   `clearToken` calls anywhere in the app immediately rehydrate this state.
 * - The `useRequireAuth()` hook redirects to /login when there's no user.
 */

import { useRouter, usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api, clearToken, hasToken, setToken, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!hasToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.me();
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearToken();
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onChange = () => refresh();
    window.addEventListener("jarvis:auth-changed", onChange);
    return () => window.removeEventListener("jarvis:auth-changed", onChange);
  }, [refresh]);

  const login = useCallback(
    async (username: string, password: string) => {
      const { access_token } = await api.login(username, password);
      setToken(access_token);
      // refresh() will fire via the event listener.
    },
    [],
  );

  const logout = useCallback(() => {
    clearToken();
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * Call from any protected page. Redirects to /login when there's no user
 * once loading finishes.
 */
export function useRequireAuth(): User | null {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (!loading && !user && pathname !== "/login") {
      router.replace("/login");
    }
  }, [loading, user, router, pathname]);
  return user;
}
