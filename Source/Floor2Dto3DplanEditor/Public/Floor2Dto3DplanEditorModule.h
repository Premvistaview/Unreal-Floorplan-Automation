// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleInterface.h"

/** Editor-only module that hosts the dockable Floor Plan Import panel. */
class FFloor2Dto3DplanEditorModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

	/** Tab id used by the Window and Tools menu entries. */
	static const FName FloorPlanImportTabId;

	/** Opens (or focuses) the Floor Plan Import panel. */
	static void OpenFloorPlanImportTab();

private:
	/** Adds Tools > Floor Plan > Floor Plan Import once the menu system is ready. */
	void RegisterMenus();
};
