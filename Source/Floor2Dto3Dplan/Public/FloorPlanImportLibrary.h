#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "FloorPlanImportLibrary.generated.h"

/** Editor file picker used by the Python floor-plan importer. */
UCLASS()
class FLOOR2DTO3DPLAN_API UFloorPlanImportLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Native OS file dialog for PNG, JPG, JPEG, PDF, DWG, and DXF. Empty if cancelled. */
	UFUNCTION(BlueprintCallable, Category = "Floor Plan")
	static FString PickFloorPlanFile();
};
