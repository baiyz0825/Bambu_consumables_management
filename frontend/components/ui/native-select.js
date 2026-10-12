import * as React from "react";

import { cn } from "../../lib/utils";

/** 与 Input 对齐：移动端 44px、16px 字号（避免 iOS 聚焦放大），桌面再收紧。 */
export const nativeSelectClassName =
  "flex h-11 w-full cursor-pointer rounded-md border border-input bg-background px-3 text-base shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 lg:h-9 lg:text-sm";

export const NativeSelect = React.forwardRef(({ className, children, ...props }, ref) => {
  return (
    <select ref={ref} className={cn(nativeSelectClassName, className)} {...props}>
      {children}
    </select>
  );
});
NativeSelect.displayName = "NativeSelect";
