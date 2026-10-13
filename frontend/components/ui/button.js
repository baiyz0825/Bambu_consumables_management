import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";

import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-full text-sm font-medium transition-[color,background-color,transform] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]",
  {
    variants: {
      variant: {
        default:
          "bg-[#0071e3] text-white hover:bg-[#0077ed] dark:bg-[#0a84ff] dark:hover:bg-[#409cff]",
        secondary:
          "bg-[#f5f5f7] text-foreground hover:bg-[#e8e8ed] dark:bg-[#2c2c2e] dark:text-white dark:hover:bg-[#3a3a3c]",
        outline:
          "border border-black/10 bg-white text-foreground hover:bg-[#f5f5f7] dark:border-white/15 dark:bg-[#1c1c1e] dark:text-white dark:hover:bg-[#2c2c2e]",
        destructive: "bg-destructive text-destructive-foreground hover:brightness-110",
        ghost: "hover:bg-[#f5f5f7] hover:text-foreground dark:hover:bg-white/10 dark:hover:text-white",
        link: "text-[#0071e3] underline-offset-4 hover:underline dark:text-[#0a84ff]"
      },
      size: {
        // 触控优先：手机 / iPad 竖屏 44px，lg（iPad 横屏与桌面）再收紧
        default: "h-11 px-4 py-2 lg:h-9",
        sm: "h-11 px-3 lg:h-8 lg:text-xs",
        lg: "h-11 px-8",
        icon: "h-11 w-11 lg:h-9 lg:w-9"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
});
Button.displayName = "Button";

export { Button, buttonVariants };

