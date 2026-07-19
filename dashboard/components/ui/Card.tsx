import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
}

export default function Card({ title, children, className, ...rest }: CardProps) {
  return (
    <div {...rest} className={["ui-card", className].filter(Boolean).join(" ")}>
      {title !== undefined && <h2 className="ui-card-title">{title}</h2>}
      {children}
    </div>
  );
}
