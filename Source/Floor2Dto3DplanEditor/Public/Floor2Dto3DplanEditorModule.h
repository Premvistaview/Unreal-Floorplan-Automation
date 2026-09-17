// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleInterface.h"

class SWallCorrectionPanel;

/**
 * What the Wall Correction window needs to know about the last detection run:
 * where the plan came from, the texture it was imported as, and the scale
 * that maps image pixels to Unreal centimetres.
 */
struct FWallCorrectionContext
{
	/** The PNG/JPG/PDF/DXF/DWG that was detected. */
	FString SourcePath;
	/** Texture2D asset the image was imported as (empty for vector sources). */
	FString TextureAssetPath;
	float PixelsPerFoot = 50.0f;
	float WallHeightCm = 300.0f;
	float DefaultThicknessCm = 15.0f;
	bool bGenerateCollision = true;
	bool bCombinedActor = true;

	float CmPerPixel() const { return PixelsPerFoot > 0.0f ? 30.48f / PixelsPerFoot : 1.0f; }
	bool HasSource() const { return !SourcePath.IsEmpty(); }
};

/** Editor-only module that hosts the Floor Plan Import panel and the Wall Correction window. */
class FFloor2Dto3DplanEditorModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

	/** Tab ids used by the Window and Tools menu entries. */
	static const FName FloorPlanImportTabId;
	static const FName WallCorrectionTabId;

	/** Opens (or focuses) the Floor Plan Import panel. */
	static void OpenFloorPlanImportTab();

	/** Opens (or focuses) the Wall Correction window, pointed at the given detection run. */
	static void OpenWallCorrection(const FWallCorrectionContext& Context);

	/** Opens the Wall Correction window with whatever context was last used. */
	static void OpenWallCorrectionTab();

	static const FWallCorrectionContext& GetLastContext() { return LastContext; }

private:
	/** Adds Tools > Floor Plan entries once the menu system is ready. */
	void RegisterMenus();

	static void SaveLastContext();
	static void LoadLastContext();

	static FWallCorrectionContext LastContext;
	static TWeakPtr<SWallCorrectionPanel> ActiveCorrectionPanel;
};
