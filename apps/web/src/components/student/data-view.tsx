"use client";

import * as React from "react";

import { ErrorState } from "@/components/states/error-state";
import { PageSkeleton } from "@/components/states/loading-state";
import { describeError, isApiError } from "@/lib/api/errors";
import type { QueryResult } from "@/lib/hooks/use-query";

/**
 * Renders a query's three states the same way everywhere: a skeleton while loading, a calm
 * error with a retry (and the API's reference id when it has one), then the content.
 */
export function DataView<T>({
  query,
  skeleton = <PageSkeleton />,
  children,
}: {
  query: QueryResult<T>;
  skeleton?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}) {
  const { state, reload } = query;
  if (state.status === "loading") return <>{skeleton}</>;
  if (state.status === "error" && state.data === undefined) {
    return (
      <ErrorState
        description={describeError(state.error)}
        reference={isApiError(state.error) ? state.error.requestId : null}
        onRetry={() => void reload()}
      />
    );
  }
  return <>{children(state.data as T)}</>;
}
