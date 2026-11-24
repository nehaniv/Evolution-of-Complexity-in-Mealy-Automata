# Supplementary group inventory only: no complexity lower-bound search.
BaselineInventory := function(generators, reachable, filename)
  local stream, sk, depth, levels, count, d, rep, x, h, p, domain, nontrivial;
  stream := OutputTextFile(filename, false);
  if stream = fail then Error("Cannot write group inventory"); fi;
  SetPrintFormattingStatus(stream, false);
  depth := 0; levels := 0; count := 0;
  if reachable > 1 then
    sk := Skeleton(Semigroup(generators));
    if DegreeOfSkeleton(sk) <> reachable then Error("Inventory degree mismatch"); fi;
    depth := Maximum(0, DepthOfSkeleton(sk)-1);
    if depth > 0 then
      for d in [1..depth] do
        rep := 0; nontrivial := false;
        for x in RepresentativeSets(sk)[d] do
          rep := rep + 1; count := count + 1;
          p := PermutatorGroup(sk, x);
          h := HolonomyGroup@SgpDec(sk, x);
          domain := ListBlist([1..reachable], x);
          PrintTo(stream, "group\t", d, "\t", rep, "\t", String(x), "\t",
            Size(h), "\t", StructureDescription(h), "\t",
            String(GeneratorsOfGroup(h)), "\t", IsSolvableGroup(h), "\t",
            String(domain), "\t", Length(domain), "\t", Size(p), "\t",
            StructureDescription(p), "\t", String(GeneratorsOfGroup(p)), "\t",
            IsSolvableGroup(p), "\n");
          if not IsTrivial(h) then nontrivial := true; fi;
        od;
        if nontrivial then levels := levels + 1; fi;
      od;
    fi;
  fi;
  PrintTo(stream, "reachable_states\t", reachable, "\n",
    "holonomy_depth\t", depth, "\n", "holonomy_group_bearing_levels\t", levels, "\n",
    "group_count\t", count, "\n", "inventory_complete\ttrue\n");
  CloseStream(stream);
end;
