import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { EmptyState } from "./states";

/**
 * DESIGN.md §8 "Table". Column definitions rather than raw `<td>`s, so the
 * numeric-alignment rule ("right-aligned with tabular figures") is applied from
 * the column's own declaration and cannot be forgotten per cell.
 */
export interface Column<Row> {
  key: string;
  header: ReactNode;
  /** Right-aligns and sets tabular figures — DESIGN.md §5. */
  numeric?: boolean;
  width?: string;
  cell: (row: Row) => ReactNode;
}

export interface DataTableProps<Row> {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** Marks the row selected: `brand.subtle` fill + 2px `primary` left border. */
  isSelected?: (row: Row) => boolean;
  onRowClick?: (row: Row) => void;
  empty?: ReactNode;
  className?: string;
}

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  isSelected,
  onRowClick,
  empty,
  className,
}: DataTableProps<Row>) {
  if (rows.length === 0) {
    return <>{empty ?? <EmptyState message="No rows to display." />}</>;
  }
  return (
    // Wide tables scroll inside their own container; the page never does.
    <div className={cn("w-full overflow-x-auto", className)}>
      <table className="w-full border-collapse text-body-md">
        <thead>
          <tr className="border-b border-border bg-muted">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  "px-table-cell-x py-table-cell-y text-label-caps uppercase text-muted-foreground",
                  column.numeric ? "text-right" : "text-left",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selected = isSelected?.(row) ?? false;
            return (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
                aria-selected={isSelected ? selected : undefined}
                className={cn(
                  "border-b border-border last:border-b-0",
                  onRowClick &&
                    "cursor-pointer focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                  selected
                    ? "border-l-2 border-l-primary bg-brand-subtle"
                    : "hover:bg-muted",
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-table-cell-x py-table-cell-y text-foreground align-middle",
                      column.numeric && "text-right tabular",
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
