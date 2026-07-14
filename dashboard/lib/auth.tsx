"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import {
  api,
  clearSession,
  getStoredUser,
  storeSession,
  type Role,
  type User,
} from "./api";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setUser(getStoredUser());
    setReady(true);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    storeSession(result.access_token, result.user);
    setUser(result.user);
    return result.user;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    router.replace("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** Gate a page to the given roles: unauthenticated users go to /login, the
 * wrong role gets a clear notice instead of the page. */
export function Protected({
  roles,
  children,
}: {
  roles: Role[];
  children: ReactNode;
}) {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  if (!ready || !user) return null;
  if (!roles.includes(user.role)) {
    return (
      <div className="empty-state">
        <h2>No access</h2>
        <p>
          This page needs one of: {roles.join(", ")}. You are signed in as{" "}
          <strong>{user.role}</strong>
          {user.role === "worker" ? " — use the mobile app for your tours." : "."}
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
