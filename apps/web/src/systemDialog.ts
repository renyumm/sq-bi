export type SystemConfirmRenderer = (
  message: string,
  resolve: (confirmed: boolean) => void,
) => void;

let confirmRenderer: SystemConfirmRenderer | null = null;

export function registerSystemConfirm(renderer: SystemConfirmRenderer): () => void {
  confirmRenderer = renderer;
  return () => {
    if (confirmRenderer === renderer) confirmRenderer = null;
  };
}

export function confirmAction(message: string): Promise<boolean> {
  if (!confirmRenderer) return Promise.resolve(window.confirm(message));
  return new Promise(resolve => confirmRenderer?.(message, resolve));
}
