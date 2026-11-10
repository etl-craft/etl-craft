import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "@radix-ui/react-slot";
import * as React from "react";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-[13px] font-medium disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_1px_2px_rgb(20_22_29/0.25)] hover:brightness-110",
        danger: "border border-bad/50 bg-surface text-bad hover:bg-bad-bg",
        dangerSolid: "bg-bad text-surface hover:opacity-90",
        outline: "bg-surface text-fg shadow-raised hover:bg-surface-2",
        ghost: "text-fg hover:bg-surface-2",
      },
      size: { md: "h-8 px-3", sm: "h-7 px-2.5", icon: "h-8 w-8" },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild, ...props }: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(button({ variant, size }), className)} {...props} />;
}
