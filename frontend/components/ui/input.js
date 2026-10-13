import * as React from "react";

import { cn } from "../../lib/utils";

const Input = React.forwardRef(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        "flex h-11 w-full rounded-xl border-0 bg-[#f5f5f7] px-3 py-1 text-base text-foreground transition-all placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0071e3] disabled:cursor-not-allowed disabled:opacity-50 lg:h-9 lg:text-sm dark:bg-[#2c2c2e] dark:text-white dark:placeholder:text-gray-500 dark:focus-visible:ring-[#0a84ff]",
        className
      )}
      ref={ref}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };

