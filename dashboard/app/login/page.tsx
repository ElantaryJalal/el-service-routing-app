"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.replace("/overview");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Invalid email or password."
          : "Could not sign in — is the backend reachable?",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <Card className="login-card">
        <h1>EL Service · Office</h1>
        <p className="muted small" style={{ marginTop: 0 }}>
          Sign in with your staff account.
        </p>
        <form onSubmit={onSubmit}>
          <Input
            label="Email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="form-error">{error}</p>}
          <Button
            variant="primary"
            type="submit"
            loading={busy}
            style={{ width: "100%" }}
          >
            Sign in
          </Button>
        </form>
      </Card>
    </div>
  );
}
