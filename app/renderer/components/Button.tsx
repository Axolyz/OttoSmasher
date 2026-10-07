// 按钮：所有页面只用这一个（React Aria 负责按压、键盘、焦点；外观来自设计令牌）。
import type { ReactNode } from "react";
import { Button as RacButton, type ButtonProps as RacButtonProps } from "react-aria-components";
import s from "./Button.module.css";

export interface ButtonProps extends Omit<RacButtonProps, "className" | "children"> {
  variant?: "primary" | "secondary" | "flat" | "danger";
  size?: "sm" | "md";
  icon?: ReactNode;
  children?: ReactNode;
  title?: string;
}

export function Button({ variant = "secondary", size = "md", icon, children, title, ...rest }: ButtonProps) {
  return (
    <RacButton {...rest} aria-label={rest["aria-label"] ?? title} className={`${s.btn} ${s[variant]} ${s[size]}`}>
      {icon ? <span className={s.icon}>{icon}</span> : null}
      {children}
    </RacButton>
  );
}
