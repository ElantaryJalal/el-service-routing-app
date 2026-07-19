"use client";

import { PageShell, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/api";
import type { ReactNode } from "react";

const NAV: { href: string; label: string; roles?: Role[] }[] = [
  { href: "/overview", label: "Overview" },
  { href: "/analytics", label: "Analytics", roles: ["manager", "admin"] },
  { href: "/tours", label: "Tours" },
  { href: "/stores", label: "Stores" },
];

/** The office frame: ui PageShell with the app's nav and signed-in user.
 * Pages pass title/subtitle/actions for the consistent page head. */
export default function AppShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { user, logout } = useAuth();
  const nav = NAV.filter(
    (item) => !item.roles || (user && item.roles.includes(user.role)),
  );

  return (
    <PageShell
      brand="EL Service · Office"
      brandHref="/overview"
      nav={nav}
      user={
        user && (
          <>
            <span>
              <strong>{user.name}</strong> · {user.role}
            </span>
            <Button size="sm" onClick={logout}>
              Sign out
            </Button>
          </>
        )
      }
      title={title}
      subtitle={subtitle}
      actions={actions}
    >
      {children}
    </PageShell>
  );
}
