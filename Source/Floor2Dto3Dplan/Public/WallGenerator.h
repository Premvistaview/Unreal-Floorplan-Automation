// Fill out your copyright notice in the Description page of Project Settings.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "WallGenerator.generated.h"

class UDynamicMeshComponent;

#if WITH_EDITOR
struct FPropertyChangedEvent;
#endif

/** One 2D wall centreline and its final wall thickness, in Unreal centimetres. */
USTRUCT(BlueprintType)
struct FLOOR2DTO3DPLAN_API FWallSegment
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall")
    FVector2D Start = FVector2D::ZeroVector;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall")
    FVector2D End = FVector2D(100.0, 0.0);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall", meta = (ClampMin = "0.1"))
    float Thickness = 15.0f;

    /**
     * 1-based index of the raw detection this wall came from, or -1 for a
     * wall added by hand. Lets Finalize report removed/added/adjusted counts
     * after the array has been edited.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall", AdvancedDisplay)
    int32 SourceIndex = -1;
};

/** Native, editor-friendly wall generator. All dimensions are Unreal centimetres. */
UCLASS(BlueprintType, Blueprintable)
class FLOOR2DTO3DPLAN_API AWallGeneratorActor : public AActor
{
    GENERATED_BODY()

public:
    AWallGeneratorActor();

    /** Root and generated wall mesh. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Wall")
    TObjectPtr<UDynamicMeshComponent> DynamicMeshComponent;

    /** Editable data; each item becomes one box-shaped wall. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall Generator")
    TArray<FWallSegment> WallSegments;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall Generator", meta = (ClampMin = "1.0"))
    float WallHeight = 300.0f;

    /** Number of valid wall boxes produced by the most recent rebuild. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Wall Generator")
    int32 GeneratedWallCount = 0;

    /**
     * Replace the editable wall data and generate the Dynamic Mesh.
     * This is the main API for Python, Blueprint, and C++ callers.
     */
    UFUNCTION(CallInEditor, BlueprintCallable, Category = "Wall Generator")
    bool GenerateWalls(
        const TArray<FWallSegment>& InWallSegments,
        float InWallHeight = 300.0f,
        bool bGenerateCollision = true);

    /** Rebuild from the current editable WallSegments and WallHeight values. */
    UFUNCTION(CallInEditor, BlueprintCallable, Category = "Wall Generator")
    bool RebuildMesh();

    /** Append one wall (undo-friendly) and rebuild. Returns the new segment's index. */
    UFUNCTION(BlueprintCallable, Category = "Wall Generator")
    int32 AddWallSegment(const FWallSegment& Segment);

    /** Remove the wall at Index (undo-friendly) and rebuild. False if Index is out of range. */
    UFUNCTION(BlueprintCallable, Category = "Wall Generator")
    bool RemoveWallSegmentAt(int32 Index);

    /** Uses the generated triangles for collision, immediately in the editor. */
    UFUNCTION(CallInEditor, BlueprintCallable, Category = "Wall Generator")
    void GenerateCollision();

    virtual void OnConstruction(const FTransform& Transform) override;

#if WITH_EDITOR
    virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif
};
