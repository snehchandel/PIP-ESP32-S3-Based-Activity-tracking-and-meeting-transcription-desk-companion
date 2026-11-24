import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import type { VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold " +
    "transition-colors disabled:pointer-events-none disabled:opacity-45 cursor-pointer select-none",
  {
    variants: {
      variant: {
        primary: "bg-ink text-paper hover:bg-ink-2",
        amber: "bg-amber text-white hover:bg-[#d06a12]",
        outline: "border border-line bg-white/70 text-ink hover:bg-paper-2",
        ghost: "text-ink-2 hover:bg-paper-2",
        danger: "border border-line bg-white/70 text-[#8a3b2e] hover:bg-[#f6e6e1]",
      },
      size: { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4", lg: "h-12 px-6 text-base", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild, type, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} type={asChild ? undefined : (type ?? "button")}
    {...props} />;
}
