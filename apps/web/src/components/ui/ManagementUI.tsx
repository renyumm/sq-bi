import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'management-primary-action',
  secondary: 'management-secondary-action',
  danger: 'management-danger-action',
  ghost: 'management-ghost-action',
};

export function ManagementPage({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`management-page ${className}`.trim()}>{children}</div>;
}

export function ManagementHeader({
  icon,
  title,
  description,
  actions,
}: {
  icon: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="management-header">
      <div className="min-w-0">
        <h1 className="management-title">{icon}{title}</h1>
        {description && <p className="management-description">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ActionButton({
  variant = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button {...props} className={`${BUTTON_VARIANTS[variant]} ${className}`.trim()} />;
}

export function ModalFrame({
  children,
  className = 'max-w-md',
  onBackdropClick,
}: {
  children: ReactNode;
  className?: string;
  onBackdropClick?: () => void;
}) {
  return (
    <div className="management-modal-backdrop" onMouseDown={onBackdropClick}>
      <div className={`management-modal-surface ${className}`.trim()} onMouseDown={event => event.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

