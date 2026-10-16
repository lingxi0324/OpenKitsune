import type { ComponentProps } from "react";
import type ReactMarkdown from "react-markdown";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { preprocessMath } from "../utils/mathPreprocess";

type Props = ComponentProps<typeof ReactMarkdown> & {
  renderer: typeof ReactMarkdown;
};

function PreprocessedMarkdown({ renderer: Renderer, children, ...props }: Props) {
  return <Renderer {...props}>{typeof children === "string" ? preprocessMath(children) : children}</Renderer>;
}

/** Isolate parser, preprocessor and renderer failures to one Markdown instance. */
export function SafeMarkdown(props: Props) {
  return (
    <ErrorBoundary
      fallback={<div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{props.children}</div>}
    >
      {/* Keep preprocessing inside the boundary too. After a failure, incoming
          streaming text keeps updating the fallback without retrying each token. */}
      <PreprocessedMarkdown {...props} />
    </ErrorBoundary>
  );
}
