# Unit test of fill_zero_weight_parameters! (prepare_for_solve.jl): only NaN cells change, to the unweighted mean of
# the members' values (a single member: its own value); esbc reads the esbt values as the package does.
# Run: julia --project=s15_har/julia s15_har/julia/test_prepare.jl  (tests/test_julia_prepare.py runs it)
using Test
include(joinpath(@__DIR__, "prepare_for_solve.jl"))

comm, reg = ["c1", "c2", "c3"], ["r1", "r2", "r3"]
comMap = NamedArray(["a", "a", "b"], comm)
regMap = NamedArray(["g1", "g1", "g2"], reg)
endMap = NamedArray(["e1"], ["e1"])
src = NamedArray([1.0 2.0 3.0; 4.0 5.0 6.0; 7.0 8.0 9.0], (comm, reg))
hPar = Dict("subp" => src, "esbt" => src, "esbc" => NamedArray(fill(99.0, 3, 3), (comm, reg)))
agg = Dict("subp" => NamedArray([0.5 NaN; NaN 0.25], (["a", "b"], ["g1", "g2"])),
           "esbc" => NamedArray([NaN 1.0; 1.0 1.0], (["a", "b"], ["g1", "g2"])))
before = copy(agg["subp"])
filled = fill_zero_weight_parameters!(agg, hPar, [comMap, regMap, endMap])
@testset "zero-weight fallback" begin
    @test agg["subp"]["a", "g1"] === before["a", "g1"]          # finite cells bit-identical
    @test agg["subp"]["b", "g2"] === before["b", "g2"]
    @test agg["subp"]["a", "g2"] == (3.0 + 6.0) / 2              # c1, c2 in r3
    @test agg["subp"]["b", "g1"] == (7.0 + 8.0) / 2              # c3 in r1, r2
    @test agg["esbc"]["a", "g1"] == (1.0 + 2.0 + 4.0 + 5.0) / 4  # from esbt, not esbc
    @test length(filled) == 3
    @test !any(isnan, agg["subp"]) && !any(isnan, agg["esbc"])
end
