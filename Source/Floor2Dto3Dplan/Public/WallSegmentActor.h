// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "WallSegmentActor.generated.h"

class UDynamicMeshComponent;

#if WITH_EDITOR
struct FPropertyChangedEvent;
#endif

/**
 * One independently selectable and editable wall.
 *
 * Start and End are local-space centreline coordinates in centimetres. Native
 * actor transforms therefore remain available for viewport correction, while
 * the Python exporter can recover the final world-space centreline.
 */
UCLASS(BlueprintType, Blueprintable)
class FLOOR2DTO3DPLAN_API AWallSegmentActor : public AActor
{
	GENERATED_BODY()

public:
	AWallSegmentActor();

	/** Root component and generated single-wall mesh. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Wall")
	TObjectPtr<UDynamicMeshComponent> DynamicMeshComponent;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall", meta = (DisplayName = "Start (Local cm)"))
	FVector2D Start = FVector2D(-100.0, 0.0);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall", meta = (DisplayName = "End (Local cm)"))
	FVector2D End = FVector2D(100.0, 0.0);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall", meta = (ClampMin = "0.1", Units = "cm"))
	float Thickness = 15.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall", meta = (ClampMin = "1.0", Units = "cm"))
	float Height = 300.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wall")
	bool bGenerateCollision = true;

	/** Set all wall dimensions in one transaction-friendly call. */
	UFUNCTION(BlueprintCallable, Category = "Wall")
	bool SetWall(
		FVector2D InStart,
		FVector2D InEnd,
		float InThickness = 15.0f,
		float InHeight = 300.0f,
		bool bInGenerateCollision = true);

	/** Rebuild this actor's one box from its current editable properties. */
	UFUNCTION(CallInEditor, BlueprintCallable, Category = "Wall")
	bool RebuildWall();

	virtual void OnConstruction(const FTransform& Transform) override;

#if WITH_EDITOR
	virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif
};
