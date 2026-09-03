// Copyright Epic Games, Inc. All Rights Reserved.

#include "FloorPlanAssetLibrary.h"

#include "AssetToolsModule.h"
#include "Components/DynamicMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Blueprint.h"
#include "Engine/StaticMeshActor.h"
#include "GeometryScript/CreateNewAssetUtilityFunctions.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "ObjectTools.h"
#include "Subsystems/EditorAssetSubsystem.h"
#include "UDynamicMesh.h"
#include "WallGenerator.h"

DEFINE_LOG_CATEGORY_STATIC(LogFloorPlanAssets, Log, All);

namespace
{
	FString NormalizeGameFolder(FString Folder)
	{
		Folder.TrimStartAndEndInline();
		Folder.ReplaceInline(TEXT("\\"), TEXT("/"));
		if (Folder.IsEmpty())
		{
			Folder = TEXT("/Game/Generated/FloorPlans");
		}
		if (!Folder.StartsWith(TEXT("/Game")))
		{
			Folder = TEXT("/Game/") + Folder.TrimChar(TEXT('/'));
		}
		Folder.RemoveFromEnd(TEXT("/"));
		return Folder;
	}

	FString MakeUniqueAssetPath(const FString& BasePackagePath)
	{
		FString UniquePackageName;
		FString UniqueAssetName;
		FAssetToolsModule::GetModule().Get().CreateUniqueAssetName(
			BasePackagePath,
			FString(),
			UniquePackageName,
			UniqueAssetName);
		return UniquePackageName;
	}
}

UBlueprint* UFloorPlanAssetLibrary::FinalizeWallGeneratorAsBlueprint(
	AWallGeneratorActor* WallGenerator,
	const FString& OutputFolder,
	const FString& BaseName,
	const bool bGenerateCollision)
{
	if (!IsValid(WallGenerator) || !IsValid(WallGenerator->DynamicMeshComponent))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Cannot finalize walls: the WallGeneratorActor is invalid."));
		return nullptr;
	}

	UDynamicMesh* DynamicMesh = WallGenerator->DynamicMeshComponent->GetDynamicMesh();
	if (!IsValid(DynamicMesh) || DynamicMesh->GetTriangleCount() == 0)
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Cannot finalize walls: the generated Dynamic Mesh is empty."));
		return nullptr;
	}

	const FString Folder = NormalizeGameFolder(OutputFolder);
	FString CleanBaseName = ObjectTools::SanitizeObjectName(BaseName);
	if (CleanBaseName.IsEmpty())
	{
		CleanBaseName = TEXT("FloorPlan");
	}

	const FString StaticMeshPath = MakeUniqueAssetPath(
		FString::Printf(TEXT("%s/SM_%s"), *Folder, *CleanBaseName));

	FGeometryScriptCreateNewStaticMeshAssetOptions MeshOptions;
	MeshOptions.bEnableRecomputeNormals = true;
	MeshOptions.bEnableRecomputeTangents = true;
	MeshOptions.bEnableCollision = bGenerateCollision;
	MeshOptions.CollisionMode = bGenerateCollision
		? ECollisionTraceFlag::CTF_UseComplexAsSimple
		: ECollisionTraceFlag::CTF_UseDefault;

	EGeometryScriptOutcomePins MeshOutcome = EGeometryScriptOutcomePins::Failure;
	UStaticMesh* StaticMesh =
		UGeometryScriptLibrary_CreateNewAssetFunctions::CreateNewStaticMeshAssetFromMesh(
			DynamicMesh,
			StaticMeshPath,
			MeshOptions,
			MeshOutcome);

	if (!IsValid(StaticMesh) || MeshOutcome != EGeometryScriptOutcomePins::Success)
	{
		UE_LOG(
			LogFloorPlanAssets,
			Error,
			TEXT("Failed to create Static Mesh asset at %s."),
			*StaticMeshPath);
		return nullptr;
	}

	UWorld* World = WallGenerator->GetWorld();
	if (!IsValid(World))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Static Mesh was created, but the editor world is unavailable."));
		return nullptr;
	}

	FActorSpawnParameters SpawnParameters;
	SpawnParameters.Name = MakeUniqueObjectName(World, AStaticMeshActor::StaticClass(), *CleanBaseName);
	SpawnParameters.ObjectFlags |= RF_Transactional;

	AStaticMeshActor* StaticMeshActor = World->SpawnActor<AStaticMeshActor>(
		AStaticMeshActor::StaticClass(),
		WallGenerator->GetActorTransform(),
		SpawnParameters);
	if (!IsValid(StaticMeshActor))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Static Mesh was created, but its temporary actor could not be spawned."));
		return nullptr;
	}

	StaticMeshActor->SetActorLabel(CleanBaseName);
	UStaticMeshComponent* StaticMeshComponent = StaticMeshActor->GetStaticMeshComponent();
	StaticMeshComponent->SetMobility(EComponentMobility::Static);
	StaticMeshComponent->SetStaticMesh(StaticMesh);
	StaticMeshComponent->SetCollisionEnabled(
		bGenerateCollision ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);

	const FString BlueprintPath = MakeUniqueAssetPath(
		FString::Printf(TEXT("%s/BP_%s"), *Folder, *CleanBaseName));

	FKismetEditorUtilities::FCreateBlueprintFromActorParams BlueprintParams;
	BlueprintParams.bReplaceActor = true;
	BlueprintParams.bKeepMobility = true;
	BlueprintParams.bOpenBlueprint = false;

	UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprintFromActor(
		BlueprintPath,
		StaticMeshActor,
		BlueprintParams);
	if (!IsValid(Blueprint))
	{
		World->DestroyActor(StaticMeshActor);
		UE_LOG(
			LogFloorPlanAssets,
			Error,
			TEXT("Static Mesh was created, but Blueprint creation failed at %s."),
			*BlueprintPath);
		return nullptr;
	}

	WallGenerator->Destroy();

	if (GEditor)
	{
		if (UEditorAssetSubsystem* AssetSubsystem = GEditor->GetEditorSubsystem<UEditorAssetSubsystem>())
		{
			AssetSubsystem->SaveLoadedAsset(StaticMesh, false);
			AssetSubsystem->SaveLoadedAsset(Blueprint, false);
		}
	}

	UE_LOG(
		LogFloorPlanAssets,
		Log,
		TEXT("Final output created: %s containing Static Mesh %s."),
		*Blueprint->GetPathName(),
		*StaticMesh->GetPathName());

	return Blueprint;
}
