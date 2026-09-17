// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "FloorPlanAssetLibrary.generated.h"

class AActor;
class AStaticMeshActor;
class AWallGeneratorActor;
class UBlueprint;

/**
 * Editor-only asset creation helpers used by the floor-plan Python router.
 */
UCLASS()
class FLOOR2DTO3DPLANEDITOR_API UFloorPlanAssetLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Converts the generated Dynamic Mesh to a Static Mesh asset, creates an
	 * Actor Blueprint containing it, replaces the source actor with a Blueprint
	 * instance, saves both assets, and returns the Blueprint asset.
	 */
	UFUNCTION(BlueprintCallable, Category = "Floor Plan")
	static UBlueprint* FinalizeWallGeneratorAsBlueprint(
		AWallGeneratorActor* WallGenerator,
		const FString& OutputFolder,
		const FString& BaseName,
		bool bGenerateCollision = true);

	/**
	 * Bake the corrected walls into one Static Mesh asset and place it in the level.
	 *
	 * Accepts either a single WallGeneratorActor (combined mode; baked in its
	 * local space and placed at its transform) or any number of per-wall
	 * actors (individual mode; merged in world space with Geometry Script's
	 * AppendMesh). The mesh gets box-projected UV0, an XAtlas lightmap UV1,
	 * recomputed normals/tangents, and — when bGenerateCollision — one
	 * oriented-box simple collision primitive per wall, falling back to
	 * complex-as-simple if none could be generated.
	 *
	 * Returns the placed Static Mesh Actor, or nullptr on failure (reasons are
	 * logged). OutStaticMeshPath receives the asset's object path.
	 */
	UFUNCTION(BlueprintCallable, Category = "Floor Plan")
	static AStaticMeshActor* BakeWallsToStaticMesh(
		const TArray<AActor*>& WallActors,
		const FString& OutputFolder,
		const FString& BaseName,
		bool bGenerateCollision,
		bool bRemoveSourceActors,
		bool bEnableNanite,
		FString& OutStaticMeshPath);
};
