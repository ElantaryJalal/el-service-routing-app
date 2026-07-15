"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import type { ReactNode } from "react";

const NAV = [
  { href: "/overview", label: "Overview" },
  { href: "/tours", label: "Tours" },
  { href: "/stores", label: "Stores" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  return (
    <>
      <header className="shell-header">
        <div className="shell-brand">
          <Link href="/overview">EL Service · Office</Link>
        </div>
        <nav className="shell-nav">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={pathname.startsWith(item.href) ? "active" : ""}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {user && (
          <div className="shell-user">
            <span>
              <strong>{user.name}</strong> · {user.role}
            </span>
            <button className="btn btn-sm" onClick={logout}>
              Sign out
            </button>
          </div>
        )}
      </header>
      <main className="page">{children}</main>
    </>
  );
}
