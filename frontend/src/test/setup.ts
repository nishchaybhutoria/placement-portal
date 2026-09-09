import "@testing-library/jest-dom/vitest";

/**
 * jsdom implements no layout, so `Element.prototype.scrollIntoView` does not
 * exist there and calling it throws. That is a gap in the environment, not
 * something the app should defend against — a real browser has always had it —
 * so it is filled here rather than by a guard in the component.
 */
Element.prototype.scrollIntoView = function scrollIntoView(): void {};
