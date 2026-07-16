import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode; }
interface State { error: Error | null; info: ErrorInfo | null; }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info });
    console.error('[SQ-BI] Render error:', error, info.componentStack);
  }

  render() {
    const { error, info } = this.state;
    if (error) {
      return (
        <div style={{
          position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', background: '#f8fafc',
          fontFamily: 'system-ui, sans-serif', padding: '24px', gap: '12px',
        }}>
          <div style={{ fontSize: 32 }}>⚠️</div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: '#1e293b', margin: 0 }}>
            页面加载出错
          </h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: 0, textAlign: 'center' }}>
            {error.message || '未知错误'}
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 8, padding: '8px 20px', background: '#1E56A0', color: '#fff',
              border: 'none', borderRadius: 8, fontSize: 13, cursor: 'pointer',
            }}
          >
            刷新页面
          </button>
          {import.meta.env.DEV && (
            <pre style={{
              marginTop: 8, padding: 12, background: '#fff', border: '1px solid #e2e8f0',
              borderRadius: 8, fontSize: 11, color: '#ef4444', maxWidth: 700,
              overflow: 'auto', maxHeight: 200, textAlign: 'left',
            }}>
              {info?.componentStack}
            </pre>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}
