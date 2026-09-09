import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/** DESIGN.md §8 "Button". Variants and sizes are exactly the table there. */
const buttonVariants = cva(
  cn(
    "inline-flex items-center justify-center gap-gap-md whitespace-nowrap rounded",
    "text-body-md font-medium transition-colors",
    "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    // Disabled never changes colour — it must not collide with a semantic one.
    "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
  ),
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/80",
        // DESIGN.md §2: an operable boundary is `border-strong`. The
        // secondary fill is a tone away from the surfaces it sits on
        // (`secondary` on `card` is 1.13:1), so the outline is the only thing
        // that says this is a button, and WCAG 1.4.11 wants 3:1 of it.
        secondary:
          "border border-border-strong bg-secondary text-foreground hover:bg-muted active:bg-secondary",
        ghost: "bg-transparent text-foreground hover:bg-muted active:bg-secondary",
        // DESIGN.md §8: the border is the fill's own colour in light and the
        // label's in dark, where a #93000a fill is 1.84:1 against card and the
        // control otherwise has no edge. Declared in both modes so the button
        // does not change size when the theme does.
        destructive:
          "border border-destructive bg-destructive text-destructive-foreground dark:border-destructive-foreground hover:bg-destructive/90 active:bg-destructive/80",
        "destructive-ghost":
          "bg-transparent text-danger hover:bg-danger-subtle active:bg-danger-subtle",
        link: "bg-transparent text-accent underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-7 px-3 text-body-sm",
        default: "h-control px-4",
        lg: "h-10 px-5",
        "icon-sm": "h-7 w-7 p-0",
        icon: "h-control w-control p-0",
        "icon-lg": "h-10 w-10 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Swaps the leading icon for a spinner and disables the button. */
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, loading = false, icon, children, disabled, ...props },
  ref,
) {
  // asChild renders a link (or anything) with button styling; the spinner and
  // the disabled coupling only make sense on a real <button>.
  if (asChild) {
    return (
      <Slot ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props}>
        {children}
      </Slot>
    );
  }
  const leading = loading ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : icon;
  return (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {leading}
      {children}
    </button>
  );
});

export { buttonVariants };
