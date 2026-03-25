import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("[ErrorBoundary] Uncaught error:", error, info);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen bg-gray-950 flex items-start justify-center pt-20 px-4">
        <div className="bg-gray-900 rounded-xl border border-red-900 p-8 max-w-md w-full">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-lg bg-red-900/40 border border-red-800 flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
            </div>
            <h2 className="text-white font-['Bebas_Neue'] text-2xl tracking-widest">
              Something went wrong
            </h2>
          </div>

          {this.state.error?.message && (
            <pre className="font-['IBM_Plex_Mono'] text-red-400 text-sm bg-red-950/30 border border-red-900/50 rounded-lg p-4 mb-6 overflow-x-auto whitespace-pre-wrap break-words">
              {this.state.error.message}
            </pre>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={() => window.location.reload()}
              className="rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-purple-600 hover:bg-purple-500 text-white text-sm"
            >
              Reload
            </button>
            <a
              href="/"
              className="rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm"
            >
              Go Home
            </a>
          </div>
        </div>
      </div>
    );
  }
}
