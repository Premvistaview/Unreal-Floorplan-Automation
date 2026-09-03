// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "FloorPlanAssetLibrary.generated.h"

class AActor;
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
};
