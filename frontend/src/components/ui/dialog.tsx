import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ComponentPropsWithoutRef, ElementRef } from "react";
import { forwardRef } from "react";

import { cn } from "@/lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

/** DESIGN.md §8 "Modal" — the only place a shadow is allowed. */
export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(function DialogContent({ className, children, ...props }, ref) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-foreground/60" />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2",
          "rounded-lg border border-border bg-popover shadow-overlay",
          "max-h-[85vh] overflow-y-auto",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          aria-label="Close"
          className="absolute right-gap-lg top-gap-lg rounded p-1 text-muted-foreground hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X aria-hidden className="h-4 w-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("border-b border-border px-container-padding py-gap-lg", className)}
      {...props}
    />
  );
}

export const DialogTitle = forwardRef<
  ElementRef<typeof DialogPrimitive.Title>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(function DialogTitle({ className, ...props }, ref) {
  return (
    <DialogPrimitive.Title
      ref={ref}
      className={cn("text-headline-md text-foreground", className)}
      {...props}
    />
  );
});

export const DialogDescription = forwardRef<
  ElementRef<typeof DialogPrimitive.Description>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(function DialogDescription({ className, ...props }, ref) {
  return (
    <DialogPrimitive.Description
      ref={ref}
      className={cn("text-body-sm text-muted-foreground", className)}
      {...props}
    />
  );
});

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-gap-md border-t border-border px-container-padding py-gap-lg",
        className,
      )}
      {...props}
    />
  );
}
