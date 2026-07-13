import { ListTodo, Rows3 } from "lucide-react";
import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const navigationItems = [
  { label: "任务库", to: "/workstation", Icon: ListTodo },
  { label: "处理队列", to: "/workstation/queue", Icon: Rows3 },
] as const;

export function Sidebar(): ReactNode {
  return (
    <aside className="ny-workstation__sidebar" aria-label="工作台导航">
      <div className="ny-workstation__brand">
        <p className="ny-workstation__eyebrow">Nyaru-Clipper</p>
        <p className="ny-workstation__brand-name">媒体工作台</p>
      </div>
      <nav className="ny-workstation__navigation" aria-label="已实现模块">
        {navigationItems.map(({ Icon, label, to }) => (
          <NavLink className="ny-workstation__navigation-link" end={to === "/workstation"} key={to} to={to}>
            <Icon aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
            {label}
          </NavLink>
        ))}
      </nav>
      <p className="ny-workstation__sidebar-note">单操作员 · 单 GPU 队列</p>
    </aside>
  );
}
