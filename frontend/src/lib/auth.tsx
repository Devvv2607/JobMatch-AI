"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, ApiError, CSRF_HEADERS, networkError, toApiError, type Session, type User } from "./api";

type AuthState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; user: User; accessToken: string; expiresIn: number };

type AuthContextValue = {
  state: AuthState;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

// Renew the access token this many seconds before it expires.
const RENEW_MARGIN_SECONDS = 60;

/**
 * Each refresh token works exactly once, and the server revokes the whole login if one
 * is presented twice. Two refreshes racing with the same cookie (React's double effect
 * in development, or two open tabs) would therefore sign the user out. Refreshes are
 * serialised: within a tab by sharing one in-flight promise, across tabs with the Web
 * Locks API. A tab that waited on the lock sends the cookie the previous holder just
 * received, because cookies are shared between tabs.
 */
let inFlightRefresh: Promise<Session | null> | null = null;

function refreshSession(): Promise<Session | null> {
  inFlightRefresh ??= withRefreshLock(requestRefresh).finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}

async function withRefreshLock<T>(work: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request("jobmatch-refresh", work);
  }
  return work();
}

async function requestRefresh(): Promise<Session | null> {
  try {
    const { data, response } = await api.POST("/api/v1/auth/refresh", {
      params: { header: CSRF_HEADERS },
    });
    return response.ok && data ? data : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const applySession = useCallback((session: Session | null) => {
    setState(
      session
        ? {
            status: "signed-in",
            user: session.user,
            accessToken: session.access_token,
            expiresIn: session.expires_in,
          }
        : { status: "signed-out" },
    );
  }, []);

  // On load, the refresh cookie (if any) restores the session.
  useEffect(() => {
    let cancelled = false;
    void refreshSession().then((session) => {
      if (!cancelled) applySession(session);
    });
    return () => {
      cancelled = true;
    };
  }, [applySession]);

  // Renew the access token shortly before it expires. Each new session re-arms this.
  const accessToken = state.status === "signed-in" ? state.accessToken : null;
  const expiresIn = state.status === "signed-in" ? state.expiresIn : 0;
  useEffect(() => {
    if (!accessToken) return;
    const delayMs = Math.max(expiresIn - RENEW_MARGIN_SECONDS, 5) * 1000;
    const timer = setTimeout(() => {
      void refreshSession().then(applySession);
    }, delayMs);
    return () => clearTimeout(timer);
  }, [accessToken, expiresIn, applySession]);

  const login = useCallback(
    async (email: string, password: string) => {
      applySession(await authenticate("/api/v1/auth/login", email, password));
    },
    [applySession],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      applySession(await authenticate("/api/v1/auth/register", email, password));
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout", { params: { header: CSRF_HEADERS } });
    } finally {
      // Signed out locally even if the request failed; the cookie expires on its own.
      applySession(null);
    }
  }, [applySession]);

  return (
    <AuthContext.Provider value={{ state, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

async function authenticate(
  path: "/api/v1/auth/login" | "/api/v1/auth/register",
  email: string,
  password: string,
): Promise<Session> {
  let result;
  try {
    result = await api.POST(path, { body: { email, password } });
  } catch {
    throw networkError();
  }
  const { data, error, response } = result;
  if (!data) throw toApiError(error, response);
  return data;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export { ApiError };
