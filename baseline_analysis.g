# Numeric bounds from the progress-aware SgpDec lower-bound implementation.
WriteBaselineFields := function(filename, fields)
  local stream, field;
  stream := OutputTextFile(filename, false);
  if stream = fail then Error("Cannot write baseline result"); fi;
  SetPrintFormattingStatus(stream, false);
  for field in fields do
    PrintTo(stream, field[1], "\t", field[2], "\n");
  od;
  PrintTo(stream, "snapshot_complete\ttrue\n");
  CloseStream(stream);
end;

AnalyzeBaseline := function(generators, reachable, directory)
  local sk, holonomy, certified, result;
  sk := Skeleton(Semigroup(generators));
  if DegreeOfSkeleton(sk) <> reachable then
    Error("Skeleton degree differs from reachable state count");
  fi;
  holonomy := Length(Filtered(GroupComponents(sk),
    level -> ForAny(level, group -> not IsTrivial(group))));
  certified := Minimum(holonomy, reachable - 1);
  WriteBaselineFields(Concatenation(directory, "/upper.tsv"), [
    ["reachable_states", reachable], ["holonomy_upper_bound", holonomy],
    ["certified_upper_bound", certified]
  ]);
  SetInfoLevel(InfoEssentialDependency, 0);
  result := MaxChainOfEssentialDependencyWithProgress(sk, rec(
    certifiedUpper := certified,
    progressFile := Concatenation(directory, "/lower-progress.txt"),
    heartbeatPairs := 100
  ));
  if not IsInt(result.lower) or result.lower < 0
      or result.lower > certified or result.upper <> certified then
    Error("Invalid complexity interval");
  fi;
  WriteBaselineFields(Concatenation(directory, "/bounds.tsv"), [
    ["lower_bound", result.lower], ["certified_upper_bound", result.upper],
    ["exact", result.exact], ["search_exhausted", result.exhausted],
    ["edge_tests", result.tests], ["lower_bound_elapsed_ms", result.elapsedMS]
  ]);
end;
