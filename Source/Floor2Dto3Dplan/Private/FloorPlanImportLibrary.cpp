#include "FloorPlanImportLibrary.h"

#if WITH_EDITOR
#include "DesktopPlatformModule.h"
#include "Framework/Application/SlateApplication.h"
#include "IDesktopPlatform.h"
#endif

FString UFloorPlanImportLibrary::PickFloorPlanFile()
{
#if WITH_EDITOR
	IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
	if (!DesktopPlatform)
	{
		return FString();
	}

	TArray<FString> OpenedFiles;
	const bool bOpened = DesktopPlatform->OpenFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		TEXT("Select Floor Plan"),
		FString(),
		TEXT(""),
		TEXT("Floor plans (*.png;*.jpg;*.jpeg;*.pdf;*.dwg;*.dxf)|*.png;*.jpg;*.jpeg;*.pdf;*.dwg;*.dxf|All files (*.*)|*.*"),
		static_cast<uint32>(EFileDialogFlags::None),
		OpenedFiles
	);

	if (bOpened && OpenedFiles.Num() > 0)
	{
		return OpenedFiles[0];
	}
#endif

	return FString();
}
