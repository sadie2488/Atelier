import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "icon" | "nav" | "text" | "close";
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ variant = "text", className = "", type = "button", ...props }, ref) {
  return <button ref={ref} type={type} className={`gallery-button gallery-button--${variant} ${className}`} {...props} />;
});
