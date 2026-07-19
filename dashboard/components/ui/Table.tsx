import type { HTMLAttributes, ReactNode } from "react";

/** Token-styled data table. Compose with plain thead/tbody/tr/th/td;
 * use <Td numeric> (or className="ui-num") for aligned tabular numbers and
 * rowProps={{ className: "ui-row-click" }} on clickable rows. */
export function Table({
  children,
  ...rest
}: HTMLAttributes<HTMLTableElement> & { children: ReactNode }) {
  return (
    <div className="ui-table-wrap">
      <table {...rest} className={["ui-table", rest.className].filter(Boolean).join(" ")}>
        {children}
      </table>
    </div>
  );
}

export function Td({
  numeric = false,
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <td
      {...rest}
      className={[numeric && "ui-num", className].filter(Boolean).join(" ") || undefined}
    >
      {children}
    </td>
  );
}

export function Th({
  numeric = false,
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <th
      {...rest}
      className={[numeric && "ui-num", className].filter(Boolean).join(" ") || undefined}
    >
      {children}
    </th>
  );
}
