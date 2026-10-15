import type { KeyboardEvent } from 'react';

// Makes a clickable table row reachable and operable from the keyboard.
export function selectableRow(selected: boolean, onSelect: () => void) {
  return {
    tabIndex: 0,
    'aria-current': selected ? ('true' as const) : undefined,
    onClick: onSelect,
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect();
      }
    },
  };
}
