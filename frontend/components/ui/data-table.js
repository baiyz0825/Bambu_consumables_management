import { cn } from "../../lib/utils";

/**
 * 窄屏（手机、iPad 竖屏）把表格行堆成卡片，操作按钮留在视口内；
 * lg（1024+，iPad 横屏 / 桌面）恢复普通表格。
 */
export function DataTable({ className, children }) {
  return (
    <div className="max-w-full overflow-x-auto rounded-md border">
      <table className={cn("data-stack w-full text-sm", className)}>{children}</table>
    </div>
  );
}

export function DataCell({ label, className, valueClassName, children }) {
  return (
    <td className={cn("px-3 py-2 align-top", className)}>
      <div className="mb-0.5 text-xs font-medium text-muted-foreground lg:hidden">{label}</div>
      <div className={cn("min-w-0 break-words", valueClassName)}>{children}</div>
    </td>
  );
}
