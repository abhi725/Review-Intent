import { Component } from "react";

/**
 * A render error anywhere below this boundary unmounts React's whole tree, and
 * without a boundary what the user gets is a white page with nothing in it — no
 * message, no clue which screen failed. That is indistinguishable from an outage
 * and it is what "the whole UI is crashing" looks like from the outside.
 *
 * So: catch it, keep the error on screen, and say which screen it came from.
 * The message is deliberately shown rather than hidden behind the console —
 * a bug report that quotes the error is worth more than one that says "blank".
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Still log it: the stack is more useful in the console than on screen.
    console.error("Dashboard render failed:", error, info?.componentStack);
  }

  // Moving to another screen should clear a failure that belonged to the old one,
  // otherwise one bad screen looks like a dead app.
  componentDidUpdate(prevProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null, info: null });
    }
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="crash">
        <h2>This screen hit an error</h2>
        <p className="note">
          The rest of the dashboard still works — switch screens to carry on. If
          this keeps happening, send the text below; it names the exact fault.
        </p>
        <pre className="crash-detail">
          {String(error?.message || error)}
          {info?.componentStack ? `\n${info.componentStack}` : ""}
        </pre>
        <button className="btn" onClick={() => this.setState({ error: null, info: null })}>
          Try again
        </button>
      </div>
    );
  }
}
