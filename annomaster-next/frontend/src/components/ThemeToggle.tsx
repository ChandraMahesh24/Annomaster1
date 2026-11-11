import { useTheme } from '../theme/ThemeProvider';

/** Dark/light switch. Icon-only, token-styled, works in both themes. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      className="btn btn-ghost"
      onClick={toggle}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      style={{ minHeight: 34, padding: '4px 10px' }}
    >
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  );
}
