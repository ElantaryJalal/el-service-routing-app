"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export interface NavItem {
  href: string;
  label: string;
}

/** Consistent app frame: sticky header (brand + nav + user area) and the
 * content column. Pages provide title/subtitle and optional head-side
 * actions; exactly one visual hierarchy per page. */
export default function PageShell({
  brand,
  brandHref = "/",
  nav = [],
  user,
  title,
  subtitle,
  actions,
  children,
}: {
  brand: string;
  brandHref?: string;
  nav?: NavItem[];
  /** Right side of the header (user name, sign out). */
  user?: ReactNode;
  title?: ReactNode;
  subtitle?: ReactNode;
  /** Right side of the page head (buttons, toggles). */
  actions?: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();
  return (
    <>
      <header className="ui-shell-header">
        <div className="ui-shell-brand">
          <Link href={brandHref}>{brand}</Link>
        </div>
        <nav className="ui-shell-nav">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={pathname.startsWith(item.href) ? "active" : ""}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {user && <div className="ui-shell-user">{user}</div>}
      </header>
      <main className="ui-page">
        {(title || actions) && (
          <div className="ui-page-head">
            <div>
              {title && <h1 className="ui-page-title">{title}</h1>}
              {subtitle && <div className="ui-page-sub">{subtitle}</div>}
            </div>
            {actions && (
              <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
                {actions}
              </div>
            )}
          </div>
        )}
        {children}
      </main>
    </>
  );
}
