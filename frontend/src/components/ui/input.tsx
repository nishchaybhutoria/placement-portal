import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** DESIGN.md §8 "Input / Select / Textarea". */
const fieldClasses = cn(
  "w-full rounded border border-input bg-card px-3 text-body-md text-foreground",
  "placeholder:text-muted-foreground",
  "focus-visible:outline-hidden focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20",
  "aria-[invalid=true]:border-danger aria-[invalid=true]:focus-visible:ring-danger/20",
  "disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-50",
);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(fieldClasses, "h-control", className)} {...props} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea ref={ref} className={cn(fieldClasses, "min-h-[72px] py-2", className)} {...props} />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...props }, ref) {
    return <select ref={ref} className={cn(fieldClasses, "h-control", className)} {...props} />;
  },
);
