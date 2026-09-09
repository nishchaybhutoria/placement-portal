import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * A square checkbox at the shape doctrine's default radius. `indeterminate` is
 * a DOM property rather than an attribute, so it is applied through the ref.
 */
export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Checkbox({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        type="checkbox"
        className={cn(
          "h-4 w-4 shrink-0 cursor-pointer rounded-sm border border-input accent-primary",
          "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);
